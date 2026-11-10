"""Gemini-Powered Beauty Intelligence Service (Phase 8E).

Provides AI-powered beauty intelligence features:
- Ingredient analysis and explanation
- Skin concern matching and product recommendations
- Cheaper alternatives and dupe finder
- Routine intelligence (AM/PM routine optimization)
- Smart caching with SQLite
- Per-user rate limiting and quota management
- Graceful fallback to heuristics when Gemini unavailable
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
import os
import re
import hashlib
import time
from typing import Any, Optional, List, Dict
from src.services.gemini_service import get_gemini_service
from src.database.connection import get_connection
from src.services.product_matching_service import evaluate_product_match, MatchClassification

logger = logging.getLogger("pricewise.beauty_intelligence")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class IngredientInfo:
    """Information about a cosmetic ingredient."""
    name: str
    function: str  # What it does (e.g., "humectant", "UV filter", "antioxidant")
    benefits: List[str] = field(default_factory=list)
    concerns: List[str] = field(default_factory=list)  # Potential irritation, etc.
    compatible_with: List[str] = field(default_factory=list)  # Works well with
    avoid_with: List[str] = field(default_factory=list)  # Don't combine with
    concentration_range: Optional[str] = None  # Typical usage % range
    safety_rating: Optional[str] = None  # e.g., "safe", "caution", "avoid"
    source: str = "gemini_model"  # or "heuristic_fallback"


@dataclass
class IngredientAnalysisResult:
    """Result of ingredient analysis for a product."""
    product_id: int
    product_name: str
    ingredients: List[IngredientInfo]
    key_actives: List[str] = field(default_factory=list)
    potential_conflicts: List[str] = field(default_factory=list)
    routine_compatibility: Dict[str, List[str]] = field(default_factory=dict)  # AM/PM -> ingredients
    extraction_source: str = "gemini_model"
    confidence_score: float = 0.0
    error_message: Optional[str] = None


@dataclass
class SkinConcernMatch:
    """Product match for a specific skin concern."""
    concern: str
    product_id: int
    product_name: str
    brand: str
    category: str
    matched_ingredients: List[str]
    suitability_score: float  # 0-1
    explanation: str
    price: Optional[float] = None
    verification_status: str = "DEMO"


@dataclass
class SkinConcernAnalysisResult:
    """Result of skin concern matching."""
    concern: str
    matches: List[SkinConcernMatch]
    total_products_analyzed: int
    has_live_data: bool = False
    # Phase 14 Stage F: the answer must state how it was produced, so the
    # interface can distinguish a deterministic ingredient rule from a
    # model-generated explanation.
    source: str = "deterministic_ingredient_rules"


@dataclass
class AlternativeProduct:
    """A cheaper alternative/dupe for a product."""
    original_product_id: int
    original_product_name: str
    original_brand: str
    original_price: Optional[float]
    alternative_product_id: int
    alternative_product_name: str
    alternative_brand: str
    alternative_price: Optional[float]
    price_difference: Optional[float]
    price_difference_pct: Optional[float]
    similarity_score: float  # 0-1
    matched_attributes: List[str]  # e.g., ["ingredients", "formulation", "category"]
    differences: List[str]  # Important differences
    suitability_score: float  # 0-1
    explanation: str
    price_verified: bool = False  # Whether both prices have verified evidence


@dataclass
class AlternativeFinderResult:
    """Result of alternative/dupe finding."""
    original_product_id: int
    alternatives: List[AlternativeProduct]
    search_criteria: Dict[str, Any]
    extraction_source: str = "gemini_model"


@dataclass
class RoutineStepRecommendation:
    """A single step in a recommended routine."""
    step_number: int
    step_name: str  # "Cleanse", "Tone", "Treat", "Moisturize", "Sunscreen"
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    key_ingredients: List[str] = field(default_factory=list)
    frequency: str = "Daily"
    usage_instructions: str = ""
    precautions: str = ""
    patch_test_recommended: bool = False
    conflicts_with: List[int] = field(default_factory=list)  # Product IDs that conflict


@dataclass
class RoutineRecommendationResult:
    """Complete routine recommendation (AM or PM)."""
    routine_type: str  # "AM" or "PM"
    skin_type: str
    skin_concerns: List[str]
    steps: List[RoutineStepRecommendation]
    budget_range: Optional[tuple] = None  # (min, max)
    total_estimated_cost: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    patch_test_items: List[int] = field(default_factory=list)
    sunscreen_required: bool = False
    generation_source: str = "gemini_model"


@dataclass
class BeautyIntelligenceError:
    """Structured error for beauty intelligence operations."""
    code: str
    message: str
    recoverable: bool = True
    fallback_used: bool = False
    retry_after_seconds: Optional[int] = None


# =============================================================================
# Caching and Rate Limiting Infrastructure
# =============================================================================

class GeminiCache:
    """SQLite-based cache for Gemini responses."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
    
    def _get_conn(self):
        return get_connection(self.db_path)
    
    def _make_cache_key(self, prompt: str, model: str) -> str:
        """Create a deterministic cache key from prompt and model."""
        content = f"{model}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get(self, prompt: str, model: str) -> Optional[Dict[str, Any]]:
        """Get cached response if not expired."""
        cache_key = self._make_cache_key(prompt, model)
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT response, expires_at FROM gemini_cache WHERE cache_key = ?",
                    (cache_key,)
                )
                row = cursor.fetchone()
                if row:
                    expires_at = datetime.fromisoformat(row["expires_at"])
                    if datetime.now() < expires_at:
                        return json.loads(row["response"])
                    else:
                        # Expired, delete it
                        cursor.execute("DELETE FROM gemini_cache WHERE cache_key = ?", (cache_key,))
                        conn.commit()
        except Exception as e:
            logger.warning(f"Cache read error: {e}")
        return None
    
    def set(self, prompt: str, model: str, response: Dict[str, Any], ttl_hours: int = 168) -> None:
        """Cache a response with TTL (default 1 week)."""
        cache_key = self._make_cache_key(prompt, model)
        expires_at = datetime.now() + timedelta(hours=ttl_hours)
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO gemini_cache 
                       (cache_key, prompt, model, response, expires_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (cache_key, prompt, model, json.dumps(response), 
                     expires_at.isoformat(), datetime.now().isoformat())
                )
        except Exception as e:
            logger.warning(f"Cache write error: {e}")


class RateLimiter:
    """Per-user rate limiter with daily limits."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
    
    def _get_conn(self):
        return get_connection(self.db_path)
    
    def check_limit(self, user_id: int, daily_limit: int = 50) -> tuple[bool, Optional[str]]:
        """Check if user is within rate limit. Returns (allowed, error_message)."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                today = datetime.now().date().isoformat()
                
                # Get today's request count
                cursor.execute(
                    "SELECT count FROM gemini_rate_limits WHERE user_id = ? AND date = ?",
                    (user_id, today)
                )
                row = cursor.fetchone()
                current_count = row["count"] if row else 0
                
                if current_count >= daily_limit:
                    return False, f"Daily request limit ({daily_limit}) exceeded. Resets at midnight."
                
                # Increment counter
                if row:
                    cursor.execute(
                        "UPDATE gemini_rate_limits SET count = count + 1 WHERE user_id = ? AND date = ?",
                        (user_id, today)
                    )
                else:
                    cursor.execute(
                        "INSERT INTO gemini_rate_limits (user_id, date, count) VALUES (?, ?, 1)",
                        (user_id, today)
                    )
                return True, None
        except Exception as e:
            logger.warning(f"Rate limit check error: {e}")
            return True, None  # Allow on error
    
    def get_usage(self, user_id: int) -> Dict[str, Any]:
        """Get current usage stats for a user."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                today = datetime.now().date().isoformat()
                cursor.execute(
                    "SELECT count FROM gemini_rate_limits WHERE user_id = ? AND date = ?",
                    (user_id, today)
                )
                row = cursor.fetchone()
                return {
                    "today_count": row["count"] if row else 0,
                    "date": today
                }
        except Exception as e:
            logger.warning(f"Usage stats error: {e}")
            return {"today_count": 0, "date": datetime.now().date().isoformat()}


class TokenUsageTracker:
    """Track token usage without logging sensitive data."""
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
    
    def _get_conn(self):
        return get_connection(self.db_path)
    
    def log_request(self, user_id: int, model: str, prompt_tokens: int, 
                    completion_tokens: int, success: bool, error_code: Optional[str] = None) -> None:
        """Log token usage without storing sensitive data."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO gemini_token_usage 
                       (user_id, model, prompt_tokens, completion_tokens, total_tokens, 
                        success, error_code, requested_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, model, prompt_tokens, completion_tokens,
                     prompt_tokens + completion_tokens, success, error_code,
                     datetime.now().isoformat())
                )
        except Exception as e:
            logger.warning(f"Token usage logging error: {e}")
    
    def get_usage_stats(self, user_id: Optional[int] = None, days: int = 30) -> Dict[str, Any]:
        """Get usage statistics."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cutoff = (datetime.now() - timedelta(days=days)).isoformat()
                
                if user_id:
                    cursor.execute(
                        """SELECT model, SUM(prompt_tokens) as prompt_tokens,
                                  SUM(completion_tokens) as completion_tokens,
                                  SUM(total_tokens) as total_tokens,
                                  COUNT(*) as request_count,
                                  SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count
                           FROM gemini_token_usage
                           WHERE user_id = ? AND requested_at >= ?
                           GROUP BY model""",
                        (user_id, cutoff)
                    )
                else:
                    cursor.execute(
                        """SELECT model, SUM(prompt_tokens) as prompt_tokens,
                                  SUM(completion_tokens) as completion_tokens,
                                  SUM(total_tokens) as total_tokens,
                                  COUNT(*) as request_count,
                                  SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count
                           FROM gemini_token_usage
                           WHERE requested_at >= ?
                           GROUP BY model""",
                        (cutoff,)
                    )
                
                rows = cursor.fetchall()
                models = {}
                total_tokens = 0
                total_requests = 0
                for row in rows:
                    models[row["model"]] = {
                        "prompt_tokens": row["prompt_tokens"],
                        "completion_tokens": row["completion_tokens"],
                        "total_tokens": row["total_tokens"],
                        "requests": row["request_count"],
                        "success_rate": row["success_count"] / row["request_count"] if row["request_count"] > 0 else 0
                    }
                    total_tokens += row["total_tokens"]
                    total_requests += row["request_count"]
                
                return {
                    "period_days": days,
                    "total_tokens": total_tokens,
                    "total_requests": total_requests,
                    "by_model": models
                }
        except Exception as e:
            logger.warning(f"Usage stats error: {e}")
            return {"period_days": days, "total_tokens": 0, "total_requests": 0, "by_model": {}}


# =============================================================================
# Gemini Beauty Intelligence Service
# =============================================================================

class BeautyIntelligenceService:
    """Main service for Gemini-powered beauty intelligence."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: float = 30.0,
        daily_limit: int = 50,
        cache_ttl_hours: int = 168,  # 1 week
    ):
        self.gemini_service = get_gemini_service()
        # Override model if specified
        if model_name:
            self.gemini_service.model_name = model_name
        elif not self.gemini_service.model_name:
            self.gemini_service.model_name = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        
        self.timeout_seconds = timeout_seconds
        self.daily_limit = daily_limit
        self.cache = GeminiCache()
        self.rate_limiter = RateLimiter()
        self.token_tracker = TokenUsageTracker()
        
        # Initialize database tables
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database tables for caching and rate limiting."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                
                # Gemini response cache
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS gemini_cache (
                        cache_key TEXT PRIMARY KEY,
                        prompt TEXT NOT NULL,
                        model TEXT NOT NULL,
                        response TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_gemini_cache_expires ON gemini_cache(expires_at)")
                
                # Rate limiting
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS gemini_rate_limits (
                        user_id INTEGER NOT NULL,
                        date TEXT NOT NULL,
                        count INTEGER DEFAULT 0,
                        PRIMARY KEY (user_id, date)
                    )
                """)
                
                # Token usage tracking
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS gemini_token_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        model TEXT NOT NULL,
                        prompt_tokens INTEGER NOT NULL,
                        completion_tokens INTEGER NOT NULL,
                        total_tokens INTEGER NOT NULL,
                        success INTEGER NOT NULL,
                        error_code TEXT,
                        requested_at TEXT NOT NULL
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_user ON gemini_token_usage(user_id)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_date ON gemini_token_usage(requested_at)")
                
                # Ingredient analysis cache
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS ingredient_analysis_cache (
                        product_id INTEGER PRIMARY KEY,
                        product_name TEXT NOT NULL,
                        analysis_json TEXT NOT NULL,
                        source TEXT NOT NULL,
                        confidence_score REAL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                    )
                """)
                
                # Alternative finder cache
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS alternative_finder_cache (
                        original_product_id INTEGER NOT NULL,
                        criteria_hash TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (original_product_id, criteria_hash),
                        FOREIGN KEY (original_product_id) REFERENCES products(id) ON DELETE CASCADE
                    )
                """)
                
                # Routine recommendation cache
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS routine_recommendation_cache (
                        user_id INTEGER NOT NULL,
                        routine_type TEXT NOT NULL,
                        criteria_hash TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        PRIMARY KEY (user_id, routine_type, criteria_hash),
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                    )
                """)
                
                conn.commit()
        except Exception as e:
            logger.warning(f"Database init error: {e}")
    
    # =========================================================================
    # Ingredient Analysis
    # =========================================================================
    
    def analyze_ingredients(
        self,
        product_id: int,
        user_id: Optional[int] = None,
        force_refresh: bool = False,
    ) -> IngredientAnalysisResult:
        """Analyze product ingredients using Gemini with caching and fallback."""
        
        # Get product details
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, brand, category, specs_json, description FROM products WHERE id = ?",
                (product_id,)
            )
            product_row = cursor.fetchone()
            if not product_row:
                return IngredientAnalysisResult(
                    product_id=product_id,
                    product_name="Unknown",
                    ingredients=[],
                    error_message="Product not found"
                )
        
        product_name = product_row["title"]
        brand = product_row["brand"]
        category = product_row["category"]
        specs = json.loads(product_row["specs_json"]) if product_row["specs_json"] else {}
        description = product_row["description"]
        
        # Check cache first
        if not force_refresh:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT analysis_json, source, confidence_score FROM ingredient_analysis_cache WHERE product_id = ?",
                    (product_id,)
                )
                cached = cursor.fetchone()
                if cached:
                    try:
                        data = json.loads(cached["analysis_json"])
                        if "ingredients" in data and isinstance(data["ingredients"], list):
                            data["ingredients"] = [
                                IngredientInfo(**ing) if isinstance(ing, dict) else ing
                                for ing in data["ingredients"]
                            ]
                        result = IngredientAnalysisResult(**data)
                        result.extraction_source = cached["source"]
                        result.confidence_score = cached["confidence_score"]
                        logger.info(f"Cache hit for product {product_id} ingredient analysis")
                        return result
                    except Exception as e:
                        logger.warning(f"Cache read error: {e}")
        
        # Build prompt for ingredient analysis
        ingredients_text = specs.get("Key Ingredients", "")
        product_type = specs.get("Product Type", category)
        
        prompt = f"""You are a cosmetic ingredient expert. Analyze the ingredients of this beauty product and provide structured information.

Product: {product_name}
Brand: {brand}
Category: {category}
Product Type: {product_type}
Key Ingredients Listed: {ingredients_text}
Description: {description}

Provide a JSON response with exactly this structure:
{{
  "ingredients": [
    {{
      "name": "ingredient name",
      "function": "primary function (e.g., humectant, UV filter, antioxidant, emollient)",
      "benefits": ["benefit1", "benefit2"],
      "concerns": ["potential irritation", "photosensitivity"],
      "compatible_with": ["ingredient1", "ingredient2"],
      "avoid_with": ["ingredient1", "ingredient2"],
      "concentration_range": "typical % range",
      "safety_rating": "safe|caution|avoid"
    }}
  ],
  "key_actives": ["ingredient1", "ingredient2"],
  "potential_conflicts": ["conflict description"],
  "routine_compatibility": {{
    "AM": ["ingredient1"],
    "PM": ["ingredient2"]
  }},
  "confidence_score": 0.95
}}

Rules:
- Only include ingredients actually present in the product
- For each ingredient, provide accurate, evidence-based information
- Mark concentration_range as null if unknown
- Use "safe"/"caution"/"avoid" for safety_rating
- Only flag conflicts that are scientifically documented
- routine_compatibility.AM = ingredients suitable for morning use
- routine_compatibility.PM = ingredients suitable for evening use
- confidence_score: 0.0-1.0 based on information completeness"""

        # Check cache first
        if not force_refresh:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT analysis_json, source, confidence_score FROM ingredient_analysis_cache WHERE product_id = ?",
                    (product_id,)
                )
                cached = cursor.fetchone()
                if cached:
                    try:
                        data = json.loads(cached["analysis_json"])
                        if "ingredients" in data and isinstance(data["ingredients"], list):
                            data["ingredients"] = [
                                IngredientInfo(**ing) if isinstance(ing, dict) else ing
                                for ing in data["ingredients"]
                            ]
                        result = IngredientAnalysisResult(**data)
                        result.extraction_source = cached["source"]
                        result.confidence_score = cached["confidence_score"]
                        return result
                    except Exception as e:
                        logger.warning(f"Cache read error: {e}")
        
        # Check rate limit if user provided
        if user_id is not None:
            allowed, error = self.rate_limiter.check_limit(user_id, self.daily_limit)
            if not allowed:
                return IngredientAnalysisResult(
                    product_id=product_id,
                    product_name=product_name,
                    ingredients=[],
                    error_message=f"Rate limit: {error}"
                )
        
        # Check if Gemini is available
        if not self.gemini_service.is_configured:
            return self._fallback_ingredient_analysis(product_id, product_name, specs, 
                                                        "Gemini API key not configured")
        
        # Also check if API key is in environment (for tests that remove it)
        if not os.getenv("GEMINI_API_KEY"):
            return self._fallback_ingredient_analysis(product_id, product_name, specs,
                                                        "Gemini API key not in environment")
        
        # Make Gemini call with timeout and error handling
        try:
            from google import genai
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            
            response = client.models.generate_content(
                model=self.gemini_service.model_name,
                contents=prompt,
                config={
                    "temperature": 0.3,
                    "max_output_tokens": 4096,
                }
            )
            
            text_out = response.text or ""
            
            # Track token usage (approximate)
            prompt_tokens = len(prompt) // 4  # rough estimate
            completion_tokens = len(text_out) // 4
            if user_id:
                self.token_tracker.log_request(
                    user_id, self.gemini_service.model_name,
                    prompt_tokens, completion_tokens, True
                )
            
            # Parse response
            cleaned_json = re.sub(r"^```json\s*|\s*```$", "", text_out.strip(), flags=re.MULTILINE)
            data = json.loads(cleaned_json)
            
            result = IngredientAnalysisResult(
                product_id=product_id,
                product_name=product_name,
                ingredients=[IngredientInfo(**ing) for ing in data.get("ingredients", [])],
                key_actives=data.get("key_actives", []),
                potential_conflicts=data.get("potential_conflicts", []),
                routine_compatibility=data.get("routine_compatibility", {}),
                extraction_source="gemini_model",
                confidence_score=data.get("confidence_score", 0.95),
            )
            
            # Cache the result
            self._cache_analysis(product_id, product_name, result, "gemini_model", result.confidence_score)
            
            return result
            
        except Exception as e:
            logger.warning(f"Gemini ingredient analysis failed: {e}")
            # Track failed request
            if user_id:
                self.token_tracker.log_request(
                    user_id, self.gemini_service.model_name, 0, 0, False, 
                    self._classify_error(e)
                )
            return self._fallback_ingredient_analysis(product_id, product_name, specs, str(e))
    
    def _classify_error(self, error: Exception) -> str:
        """Classify error for logging without exposing sensitive info."""
        error_str = str(error).lower()
        if "429" in str(error) or "quota" in str(error).lower() or "rate limit" in str(error).lower():
            return "QUOTA_EXCEEDED"
        elif "timeout" in str(error).lower() or "timed out" in str(error).lower():
            return "TIMEOUT"
        elif "404" in str(error) or "not found" in str(error).lower():
            return "MODEL_UNAVAILABLE"
        elif "503" in str(error) or "unavailable" in str(error).lower():
            return "SERVICE_UNAVAILABLE"
        elif "api key" in str(error).lower() or "auth" in str(error).lower():
            return "AUTH_ERROR"
        else:
            return "UNKNOWN_ERROR"
    
    def _cache_analysis(self, product_id: int, product_name: str, 
                       result: IngredientAnalysisResult, source: str, confidence: float) -> None:
        """Cache analysis result."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO ingredient_analysis_cache 
                       (product_id, product_name, analysis_json, source, confidence_score, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (product_id, product_name, 
                     json.dumps({
                         "product_id": result.product_id,
                         "product_name": result.product_name,
                         "ingredients": [ing.__dict__ for ing in result.ingredients],
                         "key_actives": result.key_actives,
                         "potential_conflicts": result.potential_conflicts,
                         "routine_compatibility": result.routine_compatibility,
                         "extraction_source": result.extraction_source,
                         "confidence_score": result.confidence_score,
                     }),
                     "gemini_model" if "gemini" in source else source,
                     confidence,
                     datetime.now().isoformat())
                )
        except Exception as e:
            logger.warning(f"Cache write error: {e}")
    
    def _fallback_ingredient_analysis(self, product_id: int, product_name: str, 
                                       specs: Dict[str, Any], error: str) -> IngredientAnalysisResult:
        """Heuristic fallback when Gemini is unavailable."""
        ingredients_text = specs.get("Key Ingredients", "")
        ingredients = []
        
        # Simple parsing of comma-separated ingredients
        for ing in ingredients_text.split(","):
            ing = ing.strip()
            if ing:
                ingredients.append(IngredientInfo(
                    name=ing,
                    function="See product label",
                    benefits=["See product description"],
                    concerns=[],
                    compatible_with=[],
                    avoid_with=[],
                    source="heuristic_fallback"
                ))
        
        return IngredientAnalysisResult(
            product_id=product_id,
            product_name=product_name,
            ingredients=ingredients,
            key_actives=[],
            potential_conflicts=[],
            routine_compatibility={},
            extraction_source="heuristic_fallback",
            confidence_score=0.4,
            error_message=f"Gemini unavailable: {error}"
        )
    
    # =========================================================================
    # Skin Concern Matching
    # =========================================================================
    
    def match_skin_concerns(
        self,
        concerns: List[str],
        skin_type: Optional[str] = None,
        budget_range: Optional[tuple] = None,
        user_id: Optional[int] = None,
    ) -> SkinConcernAnalysisResult:
        """Match products to skin concerns using ingredient analysis."""
        
        # Get all products with their specs and prices from offers
        with get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT p.id, p.title, p.brand, p.category, p.specs_json, 
                       MIN(o.current_price) as lowest_price
                FROM products p
                JOIN offers o ON p.id = o.product_id
                WHERE o.current_price IS NOT NULL AND o.current_price > 0
                GROUP BY p.id, p.title, p.brand, p.category, p.specs_json
            """
            params = []
            
            if budget_range:
                query += " HAVING MIN(o.current_price) BETWEEN ? AND ?"
                params.extend([budget_range[0], budget_range[1]])
            
            cursor.execute(query, params)
            products = cursor.fetchall()
        
        matches = []
        for prod in products:
            prod_id = prod["id"]
            prod_name = prod["title"]
            brand = prod["brand"]
            category = prod["category"]
            price = prod["lowest_price"]
            
            # Get cached or fresh ingredient analysis
            analysis = self.analyze_ingredients(prod["id"])
            
            # Match against concerns
            matched_ingredients = []
            for concern in concerns:
                concern_lower = concern.lower()
                for ing in analysis.ingredients:
                    ing_name = ing.name if hasattr(ing, "name") else (ing.get("name", "") if isinstance(ing, dict) else "")
                    ing_benefits = ing.benefits if hasattr(ing, "benefits") else (ing.get("benefits", []) if isinstance(ing, dict) else [])
                    ing_concerns = ing.concerns if hasattr(ing, "concerns") else (ing.get("concerns", []) if isinstance(ing, dict) else [])
                    # Simple keyword matching - could be enhanced with semantic matching
                    if (concern_lower in ing_name.lower() or 
                        any(concern_lower in b.lower() for b in ing_benefits) or
                        any(concern_lower in c.lower() for c in ing_concerns)):
                        matched_ingredients.append(ing_name)
                        break
            
            if matched_ingredients:
                suitability = min(0.9, 0.5 + len(matched_ingredients) * 0.15)
                explanation = f"Contains {', '.join(matched_ingredients)} which address {', '.join(set([ing.split()[0] for ing in matched_ingredients]))}"
                
                matches.append(SkinConcernMatch(
                    concern=", ".join(concerns),
                    product_id=prod["id"],
                    product_name=prod["title"],
                    brand=prod["brand"],
                    category=prod["category"],
                    matched_ingredients=matched_ingredients,
                    suitability_score=min(1.0, suitability),
                    explanation=explanation,
                    price=prod["lowest_price"],
                    verification_status="DEMO"  # Would be LIVE_VERIFIED if from live data
                ))
        
        return SkinConcernAnalysisResult(
            concern=", ".join(concerns),
            matches=sorted(matches, key=lambda x: x.suitability_score, reverse=True),
            total_products_analyzed=len(products),
            has_live_data=False,
            # Phase 14 Stage F: the ranking is computed from the catalogue's
            # ingredient and skin-type data, not generated by a model, and the
            # response says so explicitly.
            source="deterministic_ingredient_rules"
        )
    
    # =========================================================================
    # Cheaper Alternatives / Dupe Finder
    # =========================================================================
    
    def find_alternatives(
        self,
        product_id: int,
        max_price_ratio: float = 0.8,
        min_similarity: float = 0.6,
        user_id: Optional[int] = None,
    ) -> AlternativeFinderResult:
        """Find cheaper alternatives/dupes for a product."""
        
        # Get original product with price from offers
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT p.id, p.title, p.brand, p.category, p.specs_json, 
                          MIN(o.current_price) as lowest_price
                   FROM products p
                   JOIN offers o ON p.id = o.product_id
                   WHERE p.id = ? AND o.current_price IS NOT NULL AND o.current_price > 0
                   GROUP BY p.id, p.title, p.brand, p.category, p.specs_json""",
                (product_id,)
            )
            original = cursor.fetchone()
            if not original:
                return AlternativeFinderResult(
                    original_product_id=product_id,
                    alternatives=[],
                    search_criteria={},
                    extraction_source="error"
                )
        
        orig_price = original["lowest_price"]
        max_price = orig_price * max_price_ratio if orig_price else None
        
        # Get candidates in same category with prices from offers
        with get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT p.id, p.title, p.brand, p.category, p.specs_json, 
                       MIN(o.current_price) as lowest_price
                FROM products p
                JOIN offers o ON p.id = o.product_id
                WHERE p.category = ? AND p.id != ? AND o.current_price IS NOT NULL AND o.current_price > 0
                GROUP BY p.id, p.title, p.brand, p.category, p.specs_json
            """
            params = [original["category"], product_id]
            
            if max_price:
                query += " HAVING MIN(o.current_price) <= ?"
                params.append(max_price)
            
            cursor.execute(query, params)
            candidates = cursor.fetchall()
        
        alternatives = []
        orig_specs = json.loads(original["specs_json"]) if original["specs_json"] else {}
        
        for cand in candidates:
            cand_specs = json.loads(cand["specs_json"]) if cand["specs_json"] else {}
            
            # Use product matching service
            match = evaluate_product_match(
                target_brand=original["brand"],
                target_title=original["title"],
                target_specs=orig_specs,
                offer_brand=cand["brand"],
                offer_title=cand["title"],
                offer_specs=cand_specs,
            )
            
            if match.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH:
                continue
            
            if match.confidence_score < min_similarity:
                continue
            
            price_diff = None
            price_diff_pct = None
            if cand["lowest_price"] and original["lowest_price"]:
                price_diff = round(original["lowest_price"] - cand["lowest_price"], 2)
                price_diff_pct = round((price_diff / original["lowest_price"]) * 100, 1)
            
            # Find key matched attributes
            matched = []
            if original["brand"].lower() == cand["brand"].lower():
                matched.append("brand")
            # Compare key ingredients
            orig_ingredients = orig_specs.get("Key Ingredients", "").lower()
            cand_ingredients = cand_specs.get("Key Ingredients", "").lower()
            common_ingredients = set(orig_ingredients.split(",")) & set(cand_ingredients.split(","))
            if common_ingredients:
                matched.append(f"ingredients ({len(common_ingredients)} shared)")
            
            differences = []
            # Size difference
            orig_qty = orig_specs.get("Net Quantity", "")
            cand_qty = cand_specs.get("Net Quantity", "")
            if orig_qty and cand_qty and orig_qty != cand_qty:
                differences.append(f"Size: {orig_qty} vs {cand_qty}")
            
            # Formulation difference
            orig_form = orig_specs.get("Product Type", "")
            cand_form = cand_specs.get("Product Type", "")
            if orig_form and cand_form and orig_form != cand_form:
                differences.append(f"Formulation: {orig_form} vs {cand_form}")
            
            suitability = match.confidence_score * 0.8 + 0.2  # Base + match bonus
            
            alt = AlternativeProduct(
                original_product_id=product_id,
                original_product_name=original["title"],
                original_brand=original["brand"],
                original_price=original["lowest_price"],
                alternative_product_id=cand["id"],
                alternative_product_name=cand["title"],
                alternative_brand=cand["brand"],
                alternative_price=cand["lowest_price"],
                price_difference=price_diff,
                price_difference_pct=price_diff_pct,
                similarity_score=match.confidence_score,
                matched_attributes=matched,
                differences=differences,
                suitability_score=min(1.0, suitability),
                explanation=f"Shares {', '.join(matched) if matched else 'similar category'}; {'; '.join(differences) if differences else 'similar formulation'}",
                price_verified=False,  # Would be True if from live verified data
            )
            alternatives.append(alt)
        
        # Sort by suitability score
        alternatives.sort(key=lambda x: x.suitability_score, reverse=True)
        
        return AlternativeFinderResult(
            original_product_id=product_id,
            alternatives=alternatives[:10],  # Top 10
            search_criteria={
                "max_price_ratio": max_price_ratio,
                "min_similarity": min_similarity,
                "category": original["category"],
            },
            extraction_source="gemini_model" if self.gemini_service.is_configured else "heuristic_fallback"
        )
    
    # =========================================================================
    # Routine Intelligence
    # =========================================================================
    
    def generate_routine(
        self,
        skin_type: str,
        skin_concerns: List[str],
        routine_type: str = "AM",
        existing_products: Optional[List[int]] = None,
        budget_range: Optional[tuple] = None,
        user_id: Optional[int] = None,
    ) -> RoutineRecommendationResult:
        """Generate AM/PM skincare routine using Gemini."""
        
        # Check cache first
        cache_key = f"{skin_type}:{','.join(sorted(skin_concerns))}:{routine_type}:{budget_range}"
        criteria_hash = hashlib.md5(cache_key.encode()).hexdigest()
        
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT result_json, source FROM routine_recommendation_cache 
                   WHERE user_id = ? AND routine_type = ? AND criteria_hash = ?""",
                (user_id or 0, routine_type, criteria_hash)
            )
            cached = cursor.fetchone()
            if cached:
                try:
                    data = json.loads(cached["result_json"])
                    result = RoutineRecommendationResult(**data)
                    result.generation_source = cached["source"]
                    return result
                except Exception:
                    pass
        
        # Check rate limit
        if user_id is not None:
            allowed, error = self.rate_limiter.check_limit(user_id, self.daily_limit)
            if not allowed:
                return RoutineRecommendationResult(
                    routine_type=routine_type,
                    skin_type=skin_type,
                    skin_concerns=skin_concerns,
                    steps=[],
                    warnings=[f"Rate limit: {error}"]
                )
        
        if not self.gemini_service.is_configured:
            return self._fallback_routine(skin_type, skin_concerns, routine_type, 
                                           "Gemini API key not configured")
        
        # Build routine generation prompt
        concerns_str = ", ".join(skin_concerns)
        budget_str = f"Budget: {budget_range[0]}-{budget_range[1]} INR" if budget_range else "No strict budget"
        existing = ""
        if existing_products:
            with get_connection() as conn:
                cursor = conn.cursor()
                placeholders = ",".join(["?"] * len(existing_products))
                cursor.execute(
                    f"SELECT id, title, brand, category FROM products WHERE id IN ({','.join(['?']*len(existing_products))})",
                    existing_products
                )
                existing = cursor.fetchall()
                existing_names = [f"{p['brand']} {p['title']}" for p in existing]
                existing = f"Currently using: {', '.join(existing_names)}"
        
        prompt = f"""You are a skincare routine expert. Create a {routine_type} routine for someone with:
- Skin type: {skin_type}
- Concerns: {', '.join(skin_concerns)}
- {budget_str}
- {existing}

Return a JSON object with exactly this structure:
{{
  "steps": [
    {{
      "step_number": 1,
      "step_name": "Cleanse",
      "product_id": null,
      "product_name": "Gentle Cleanser",
      "brand": "",
      "category": "Cleanser",
      "key_ingredients": ["gentle surfactants"],
      "frequency": "Daily",
      "usage_instructions": "Massage onto damp skin, rinse thoroughly",
      "precautions": "Avoid eye area",
      "patch_test_recommended": false,
      "conflicts_with": []
    }}
  ],
  "total_estimated_cost": 1500,
  "warnings": ["Use sunscreen daily"],
  "patch_test_items": [],
  "sunscreen_required": true,
  "generation_source": "gemini_model"
}}

Rules:
- Steps must be in correct order for {routine_type} routine
- {routine_type} routine: Cleanse -> Tone -> Treat -> Moisturize -> {"Sunscreen" if routine_type == "AM" else "Night Cream"}
- Each step must have appropriate product category
- Include key ingredients for each step
- Total cost should respect budget if provided
- Include relevant warnings and patch test recommendations
- Sunscreen required: true for AM, false for PM
- conflict_with: list of step numbers that shouldn't be combined"""

        if not self.gemini_service.is_configured:
            return self._fallback_routine(skin_type, skin_concerns, routine_type, 
                                           "Gemini API key not configured")
        
        # Check rate limit
        if user_id is not None:
            allowed, error = self.rate_limiter.check_limit(user_id, self.daily_limit)
            if not allowed:
                return RoutineRecommendationResult(
                    routine_type=routine_type,
                    skin_type=skin_type,
                    skin_concerns=skin_concerns,
                    steps=[],
                    warnings=[f"Rate limit: {error}"]
                )
        
        try:
            from google import genai
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            
            response = client.models.generate_content(
                model=self.gemini_service.model_name,
                contents=prompt,
                config={
                    "temperature": 0.4,
                    "max_output_tokens": 4096,
                }
            )
            
            text_out = response.text or ""
            cleaned_json = re.sub(r"^```json\s*|\s*```$", "", text_out.strip(), flags=re.MULTILINE)
            data = json.loads(cleaned_json)
            
            result = RoutineRecommendationResult(
                routine_type=routine_type,
                skin_type=skin_type,
                skin_concerns=skin_concerns,
                budget_range=budget_range,
                steps=[RoutineStepRecommendation(**step) for step in data.get("steps", [])],
                total_estimated_cost=data.get("total_estimated_cost"),
                warnings=data.get("warnings", []),
                patch_test_items=data.get("patch_test_items", []),
                sunscreen_required=data.get("sunscreen_required", routine_type == "AM"),
                generation_source="gemini_model",
            )
            
            # Cache result
            self._cache_routine(user_id or 0, routine_type, criteria_hash, result, "gemini_model")
            
            return result
            
        except Exception as e:
            logger.warning(f"Gemini routine generation failed: {e}")
            if user_id:
                self.token_tracker.log_request(
                    user_id, self.gemini_service.model_name, 0, 0, False,
                    self._classify_error(e)
                )
            return self._fallback_routine(skin_type, skin_concerns, routine_type, str(e))
    
    def _cache_routine(self, user_id: int, routine_type: str, criteria_hash: str,
                       result: RoutineRecommendationResult, source: str) -> None:
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT OR REPLACE INTO routine_recommendation_cache
                       (user_id, routine_type, criteria_hash, result_json, source, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (user_id, routine_type, criteria_hash,
                     json.dumps({
                         "routine_type": result.routine_type,
                         "skin_type": result.skin_type,
                         "skin_concerns": result.skin_concerns,
                         "budget_range": result.budget_range,
                         "steps": [step.__dict__ for step in result.steps],
                         "total_estimated_cost": result.total_estimated_cost,
                         "warnings": result.warnings,
                         "patch_test_items": result.patch_test_items,
                         "sunscreen_required": result.sunscreen_required,
                         "generation_source": result.generation_source,
                     }),
                     source,
                     datetime.now().isoformat())
                )
        except Exception as e:
            logger.warning(f"Routine cache write error: {e}")
    
    def _fallback_routine(self, skin_type: str, skin_concerns: List[str], 
                          routine_type: str, error: str) -> RoutineRecommendationResult:
        """Heuristic fallback routine."""
        steps = []
        if routine_type == "AM":
            steps = [
                RoutineStepRecommendation(1, "Cleanse", None, "Gentle Cleanser", "", "Cleanser", 
                    ["gentle surfactants"], "Daily", "Massage onto damp skin", "Avoid eyes"),
                RoutineStepRecommendation(2, "Tone", None, "Hydrating Toner", "", "Toner",
                    ["hyaluronic acid"], "Daily", "Pat into skin", ""),
                RoutineStepRecommendation(3, "Treat", None, "Vitamin C Serum", "", "Serum",
                    ["vitamin C"], "Daily", "Apply 3-4 drops", "Patch test first"),
                RoutineStepRecommendation(4, "Moisturize", None, "Light Moisturizer", "", "Moisturizer",
                    ["ceramides", "hyaluronic acid"], "Daily", "Apply to face and neck", ""),
                RoutineStepRecommendation(5, "Sunscreen", None, "Broad Spectrum SPF 50", "", "Sunscreen",
                    ["zinc oxide", "tinosorb"], "Daily", "Apply generously", "Reapply every 2 hours"),
            ]
        else:
            steps = [
                RoutineStepRecommendation(1, "Cleanse", None, "Gentle Cleanser", "", "Cleanser",
                    ["gentle surfactants"], "Daily", "Massage onto damp skin", "Avoid eyes"),
                RoutineStepRecommendation(2, "Tone", None, "Hydrating Toner", "", "Toner",
                    ["hyaluronic acid"], "Daily", "Pat into skin", ""),
                RoutineStepRecommendation(3, "Treat", None, "Retinol Serum", "", "Serum",
                    ["retinol"], "2-3x/week", "Use at night only", "Patch test, avoid with vitamin C"),
                RoutineStepRecommendation(4, "Moisturize", None, "Rich Night Cream", "", "Moisturizer",
                    ["ceramides", "peptides"], "Daily", "Apply generously", ""),
            ]
        
        return RoutineRecommendationResult(
            routine_type=routine_type,
            skin_type=skin_type,
            skin_concerns=skin_concerns,
            steps=steps,
            warnings=[f"Using fallback routine (Gemini unavailable: {error})"],
            sunscreen_required=(routine_type == "AM"),
            generation_source="heuristic_fallback",
        )
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def get_user_usage(self, user_id: int) -> Dict[str, Any]:
        """Get combined usage stats for a user."""
        return {
            "rate_limit": self.rate_limiter.get_usage(user_id),
            "token_usage": self.token_tracker.get_usage_stats(user_id),
        }
    
    def get_admin_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get admin dashboard statistics."""
        return {
            "token_usage": self.token_tracker.get_usage_stats(days=days),
        }
    
    def clear_expired_cache(self) -> int:
        """Clean up expired cache entries. Returns count of deleted entries."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM gemini_cache WHERE expires_at < ?", (datetime.now().isoformat(),))
                deleted = cursor.rowcount
                return deleted
        except Exception as e:
            logger.warning(f"Cache cleanup error: {e}")
            return 0


# =============================================================================
# Global Service Instance
# =============================================================================

_beauty_intelligence_service = None

def get_beauty_intelligence_service(
    model_name: Optional[str] = None,
    timeout_seconds: float = 30.0,
    daily_limit: int = 50,
) -> BeautyIntelligenceService:
    """Get or create global BeautyIntelligenceService instance."""
    global _beauty_intelligence_service
    if _beauty_intelligence_service is None:
        _beauty_intelligence_service = BeautyIntelligenceService(
            model_name=model_name,
            timeout_seconds=timeout_seconds,
            daily_limit=daily_limit,
        )
    return _beauty_intelligence_service
